package com.gzalo.poslaroid

import android.Manifest
import android.annotation.SuppressLint
import android.content.ContentValues
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Color
import android.os.Build
import android.os.Bundle
import android.provider.MediaStore
import android.util.Log
import android.view.View
import android.view.WindowManager
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageCapture
import androidx.camera.core.ImageCaptureException
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.core.content.ContextCompat
import com.dantsu.escposprinter.EscPosPrinter
import com.dantsu.escposprinter.connection.bluetooth.BluetoothConnection
import com.dantsu.escposprinter.connection.bluetooth.BluetoothPrintersConnections
import com.dantsu.escposprinter.textparser.PrinterTextParserImg
import com.gzalo.poslaroid.databinding.ActivityMainBinding
import java.io.ByteArrayOutputStream
import java.io.InputStream
import java.net.HttpURLConnection
import java.net.URL
import java.text.SimpleDateFormat
import java.util.Locale
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors


class MainActivity : AppCompatActivity() {
    private lateinit var viewBinding: ActivityMainBinding

    private var imageCapture: ImageCapture? = null
    private lateinit var cameraExecutor: ExecutorService
    private var flashMode: Int = ImageCapture.FLASH_MODE_OFF
    private var cameraSelector = CameraSelector.DEFAULT_FRONT_CAMERA
    private var printer: EscPosPrinter? = null
    private var connection: BluetoothConnection? = null

    // Store the captured bitmap for style processing
    private var capturedBitmap: Bitmap? = null

    @SuppressLint("MissingPermission")
    @SuppressWarnings("deprecation")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        viewBinding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(viewBinding.root)

        getWindow().setFlags(
            WindowManager.LayoutParams.FLAG_FULLSCREEN,
            WindowManager.LayoutParams.FLAG_FULLSCREEN);
        getSupportActionBar()?.hide();

        if (allPermissionsGranted()) {
            startCamera()
        } else {
            requestPermissions()
        }

        viewBinding.imageCaptureButton.setOnClickListener { takePhoto() }
        viewBinding.flashToggleButton.setOnClickListener { toggleFlash() }
        viewBinding.switchCamera.setOnClickListener { switchCamera() }
        viewBinding.mirrorCamera.setOnClickListener { mirrorCamera() }

        // Setup style button click listeners
        viewBinding.styleNormal.setOnClickListener { onStyleSelected(null) }
        viewBinding.styleCartoon.setOnClickListener { onStyleSelected("cartoon") }
        viewBinding.styleAnime.setOnClickListener { onStyleSelected("anime") }
        viewBinding.styleSketch.setOnClickListener { onStyleSelected("pencil sketch") }
        viewBinding.styleOilPainting.setOnClickListener { onStyleSelected("oil painting") }
        viewBinding.stylePixelArt.setOnClickListener { onStyleSelected("pixel art") }

        cameraExecutor = Executors.newSingleThreadExecutor()

        connection = BluetoothPrintersConnections.selectFirstPaired()
        if (connection == null){
            Toast.makeText(baseContext, "Es necesario ir a los ajustes de bluetooth y vincular la impresora", Toast.LENGTH_SHORT).show()
        } else {
            Toast.makeText(baseContext, "Conectado al dispositivo: " + connection?.device?.name, Toast.LENGTH_SHORT).show()
        }
        printer = EscPosPrinter(connection, 203, 48f, 32)
    }

    private fun mirrorCamera() {
        viewBinding.viewFinder.scaleX *= -1f
    }

    private fun requestPermissions() {
        activityResultLauncher.launch(REQUIRED_PERMISSIONS)
    }

    private fun allPermissionsGranted() = REQUIRED_PERMISSIONS.all {
        ContextCompat.checkSelfPermission(
            baseContext, it) == PackageManager.PERMISSION_GRANTED
    }

    private fun switchCamera() {
        when (cameraSelector){
            CameraSelector.DEFAULT_BACK_CAMERA -> {
                cameraSelector = CameraSelector.DEFAULT_FRONT_CAMERA
            }
            CameraSelector.DEFAULT_FRONT_CAMERA -> {
                cameraSelector = CameraSelector.DEFAULT_BACK_CAMERA
            }
        }
        startCamera()
    }

    private fun toggleFlash() {
        when (flashMode) {
            ImageCapture.FLASH_MODE_OFF -> {
                flashMode = ImageCapture.FLASH_MODE_ON;
                viewBinding.flashToggleButton.setText(R.string.flash_turn_off);
            }
            ImageCapture.FLASH_MODE_ON -> {
                flashMode = ImageCapture.FLASH_MODE_OFF
                viewBinding.flashToggleButton.setText(R.string.flash_turn_on);
            }
        }

        imageCapture?.flashMode = flashMode;
    }

    private fun takePhoto() {
        // Show initial message
        viewBinding.printing.text = getString(R.string.preparing_photo)
        viewBinding.printing.visibility = View.VISIBLE
        viewBinding.viewFinder.visibility = View.INVISIBLE

        viewBinding.flashToggleButton.visibility = View.INVISIBLE
        viewBinding.switchCamera.visibility = View.INVISIBLE
        viewBinding.mirrorCamera.visibility = View.INVISIBLE
        viewBinding.footerText.visibility = View.INVISIBLE
        viewBinding.apiUrl.visibility = View.INVISIBLE
        viewBinding.imageCaptureButton.visibility = View.INVISIBLE

        val imageCapture = imageCapture ?: return

        val date = System.currentTimeMillis()

        val name = SimpleDateFormat(FILENAME_FORMAT, Locale.US)
            .format(date)
        val contentValues = ContentValues().apply {
            put(MediaStore.MediaColumns.DISPLAY_NAME, name)
            put(MediaStore.MediaColumns.MIME_TYPE, "image/jpeg")
            if(Build.VERSION.SDK_INT > Build.VERSION_CODES.P) {
                put(MediaStore.Images.Media.RELATIVE_PATH, "Pictures/CameraX-Image")
            }
        }

        val outputOptions = ImageCapture.OutputFileOptions
            .Builder(contentResolver,
                MediaStore.Images.Media.EXTERNAL_CONTENT_URI,
                contentValues)
            .build()

        val context = this

        imageCapture.takePicture(
            outputOptions,
            ContextCompat.getMainExecutor(this),
            object : ImageCapture.OnImageSavedCallback {
                override fun onError(exc: ImageCaptureException) {
                    Log.e(TAG, "Sacar foto falló: ${exc.message}", exc)
                    resetUI()
                }

                override fun onImageSaved(output: ImageCapture.OutputFileResults){
                    val inputStream: InputStream = context.contentResolver.openInputStream(output.savedUri ?: return) ?: return
                    capturedBitmap = BitmapFactory.decodeStream(inputStream)
                    inputStream.close()

                    // Show style selection grid with preview
                    runOnUiThread {
                        viewBinding.printing.visibility = View.INVISIBLE
                        viewBinding.previewImage.setImageBitmap(capturedBitmap)
                        viewBinding.styleSelectionContainer.visibility = View.VISIBLE
                    }
                }
            }
        )
    }

    private fun onStyleSelected(style: String?) {
        val bitmap = capturedBitmap ?: return

        // Hide style selection, show processing message
        viewBinding.styleSelectionContainer.visibility = View.GONE
        viewBinding.printing.visibility = View.VISIBLE

        if (style == null) {
            // Normal mode - just print directly
            viewBinding.printing.text = getString(R.string.sending_to_printer)
            Thread {
                printBluetooth(bitmap)
                runOnUiThread { resetUI() }
            }.start()
        } else {
            // Process through API with selected style
            Thread {
                runOnUiThread {
                    viewBinding.printing.text = getString(R.string.processing_cartoon)
                }

                val processedBitmap = processStyleApi(bitmap, style)
                val finalBitmap = processedBitmap ?: bitmap

                if (processedBitmap == null) {
                    runOnUiThread {
                        Toast.makeText(baseContext, "Error en procesamiento, usando foto original", Toast.LENGTH_SHORT).show()
                    }
                }

                runOnUiThread {
                    viewBinding.printing.text = getString(R.string.sending_to_printer)
                }

                printBluetooth(finalBitmap)
                runOnUiThread { resetUI() }
            }.start()
        }
    }

    private fun resetUI() {
        capturedBitmap = null
        viewBinding.viewFinder.visibility = View.VISIBLE
        viewBinding.printing.visibility = View.INVISIBLE
        viewBinding.styleSelectionContainer.visibility = View.GONE
        /*viewBinding.flashToggleButton.visibility = View.VISIBLE
        viewBinding.switchCamera.visibility = View.VISIBLE
        viewBinding.mirrorCamera.visibility = View.VISIBLE
        viewBinding.footerText.visibility = View.VISIBLE*/
        viewBinding.imageCaptureButton.visibility = View.VISIBLE
    }

    private fun processStyleApi(bitmap: Bitmap, style: String): Bitmap? {
        try {
            val apiUrlText = viewBinding.apiUrl.text.toString()
            val url = URL(apiUrlText)
            val httpConnection = url.openConnection() as HttpURLConnection
            httpConnection.requestMethod = "POST"
            httpConnection.doOutput = true
            httpConnection.doInput = true
            httpConnection.setRequestProperty("Content-Type", "multipart/form-data; boundary=----WebKitFormBoundary")

            val boundary = "----WebKitFormBoundary"
            val outputStream = httpConnection.outputStream

            // Convert bitmap to JPEG bytes
            val byteArrayOutputStream = ByteArrayOutputStream()
            bitmap.compress(Bitmap.CompressFormat.JPEG, 90, byteArrayOutputStream)
            val imageBytes = byteArrayOutputStream.toByteArray()

            // Write multipart form data with image
            val writer = outputStream.bufferedWriter()
            writer.write("--$boundary\r\n")
            writer.write("Content-Disposition: form-data; name=\"image\"; filename=\"input.jpg\"\r\n")
            writer.write("Content-Type: image/jpeg\r\n\r\n")
            writer.flush()
            outputStream.write(imageBytes)
            outputStream.flush()

            // Add style field
            writer.write("\r\n--$boundary\r\n")
            writer.write("Content-Disposition: form-data; name=\"style\"\r\n\r\n")
            writer.write(style)
            writer.write("\r\n--$boundary--\r\n")
            writer.flush()
            writer.close()

            val responseCode = httpConnection.responseCode
            if (responseCode == HttpURLConnection.HTTP_OK) {
                val responseStream = httpConnection.inputStream
                val resultBitmap = BitmapFactory.decodeStream(responseStream)
                responseStream.close()
                httpConnection.disconnect()
                return resultBitmap
            } else {
                Log.e(TAG, "Style API error: $responseCode")
                httpConnection.disconnect()
                return null
            }
        } catch (e: Exception) {
            Log.e(TAG, "Style API exception: ${e.message}", e)
            return null
        }
    }

    private fun printBluetooth(bitmap: Bitmap) {
        try {
            Log.i(TAG, "starting print")
            val resizedBitmap = Bitmap.createScaledBitmap(bitmap, 384, (384 * bitmap.height / bitmap.width.toFloat()).toInt(), true)
            Log.i(TAG, "resized")
            val grayscaleBitmap = toGrayscale(resizedBitmap)
            Log.i(TAG, "grayscaled")
            val ditheredBitmap = floydSteinbergDithering(grayscaleBitmap)
            Log.i(TAG, "floydsteinberg")

            val text = StringBuilder()
            for (y in 0 until ditheredBitmap.height step 32) {
                val segmentHeight =
                    if (y + 32 > ditheredBitmap.height) ditheredBitmap.height - y else 32
                val segment =
                    Bitmap.createBitmap(ditheredBitmap, 0, y, ditheredBitmap.width, segmentHeight)
                text.append(
                    "<img>" + PrinterTextParserImg.bitmapToHexadecimalString(
                        printer,
                        segment,
                        false
                    ) + "</img>\n"
                )
            }

            connection?.connect()
            printer?.printFormattedText( text.toString() + viewBinding.footerText.text)
            Thread.sleep(3000);
            connection?.disconnect()
        } catch (e: Exception) {
            Log.e(TAG, "Print error: ${e.message}", e)
            runOnUiThread {
                Toast.makeText(baseContext, "Error de impresión: ${e.message}", Toast.LENGTH_LONG).show()
            }
        }
    }

    fun toGrayscale(bitmap: Bitmap): Bitmap {
        val width = bitmap.width
        val height = bitmap.height
        val pixels = IntArray(width * height)
        bitmap.getPixels(pixels, 0, width, 0, 0, width, height)

        val grayPixels = IntArray(width * height)

        for (i in pixels.indices) {
            val pixel = pixels[i]
            val red = (pixel shr 16) and 0xFF
            val green = (pixel shr 8) and 0xFF
            val blue = pixel and 0xFF
            val gray = (0.3 * red + 0.59 * green + 0.11 * blue).toInt()
            val grayPixel = (0xFF shl 24) or (gray shl 16) or (gray shl 8) or gray
            grayPixels[i] = grayPixel
        }

        val grayBitmap = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888)
        grayBitmap.setPixels(grayPixels, 0, width, 0, 0, width, height)

        return grayBitmap
    }

    fun floydSteinbergDithering(bitmap: Bitmap): Bitmap {
        val width = bitmap.width
        val height = bitmap.height
        val ditheredBitmap = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888)

        val pixels = IntArray(width * height)
        bitmap.getPixels(pixels, 0, width, 0, 0, width, height)

        val errorDiffusionMatrix = arrayOf(
            intArrayOf(0, 0, 0, 7),
            intArrayOf(3, 5, 1, 0)
        )

        for (y in 0 until height) {
            for (x in 0 until width) {
                val index = y * width + x
                val oldPixel = pixels[index]
                val oldGray = Color.red(oldPixel)
                val newGray = if (oldGray > 128) 255 else 0
                val error = oldGray - newGray

                pixels[index] = Color.rgb(newGray, newGray, newGray)

                for (dy in errorDiffusionMatrix.indices) {
                    for (dx in errorDiffusionMatrix[dy].indices) {
                        val newX = x + dx - 1
                        val newY = y + dy
                        if (newX < 0 || newX >= width || newY >= height) continue
                        val newIndex = newY * width + newX
                        val pixel = pixels[newIndex]
                        val gray = Color.red(pixel)
                        val newGrayValue = (gray + error * errorDiffusionMatrix[dy][dx] / 16).coerceIn(0, 255)
                        pixels[newIndex] = Color.rgb(newGrayValue, newGrayValue, newGrayValue)
                    }
                }
            }
        }

        ditheredBitmap.setPixels(pixels, 0, width, 0, 0, width, height)
        return ditheredBitmap
    }

    private fun startCamera() {

        val cameraProviderFuture = ProcessCameraProvider.getInstance(this)

        cameraProviderFuture.addListener({
            val cameraProvider: ProcessCameraProvider = cameraProviderFuture.get()

            val preview = Preview.Builder()
                .build()
                .also {
                    it.setSurfaceProvider(viewBinding.viewFinder.surfaceProvider)
                }

            imageCapture = ImageCapture.Builder()
                .build()

            viewBinding.viewFinder.scaleX = -1f

            try {
                cameraProvider.unbindAll()

                cameraProvider.bindToLifecycle(
                    this, cameraSelector, preview, imageCapture)

            } catch(exc: Exception) {
                Log.e(TAG, "Use case binding failed", exc)
            }

        }, ContextCompat.getMainExecutor(this))
    }

    override fun onDestroy() {
        super.onDestroy()
        cameraExecutor.shutdown()
    }

    companion object {
        private const val TAG = "CameraXApp"
        private const val FILENAME_FORMAT = "yyyy-MM-dd-HH-mm-ss-SSS"
        private val REQUIRED_PERMISSIONS =
            mutableListOf (
                Manifest.permission.CAMERA,
                Manifest.permission.RECORD_AUDIO,
                Manifest.permission.BLUETOOTH,
                Manifest.permission.BLUETOOTH_ADMIN,
                Manifest.permission.BLUETOOTH_CONNECT,
                Manifest.permission.BLUETOOTH_SCAN
            ).apply {
                if (Build.VERSION.SDK_INT <= Build.VERSION_CODES.P) {
                    add(Manifest.permission.WRITE_EXTERNAL_STORAGE)
                }
            }.toTypedArray()
    }

    private val activityResultLauncher =
        registerForActivityResult(
            ActivityResultContracts.RequestMultiplePermissions())
        { _ -> startCamera()
        }
}
